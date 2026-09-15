import asyncio
import ipaddress
import json
from pathlib import Path
import plistlib
import socket
import ssl
import tempfile
import unittest
import numpy as np
from aiohttp import ClientSession, WSServerHandshakeError, WSMsgType
from aiohttp.test_utils import TestServer
from cryptography import x509
from audio_engine import LiveBuffer, Resampler
from certificates import prepare
from server import MicServer


class AudioTests(unittest.TestCase):
    def test_streaming_resample_preserves_tone_across_chunks(self):
        for source,target in [(44100,48000),(48000,44100),(48000,48000)]:
            x=np.sin(2*np.pi*440*np.arange(source)/source).astype(np.float32)
            resampler=Resampler(source,target)
            chunks=[resampler.process(x[n:n+960]) for n in range(0,len(x),960)]
            y=np.concatenate(chunks)
            self.assertLessEqual(abs(len(y)-target),2)
            expected=np.sin(2*np.pi*440*np.arange(len(y))/target)
            self.assertLess(float(np.max(np.abs(y-expected))),.001)

    def test_queue_prefill_wrap_stereo_and_clear(self):
        q=LiveBuffer(1000)
        out=np.zeros((40,2),dtype=np.float32)
        q.push(np.ones(30));q.fill(out);self.assertFalse(out.any())
        q.push(np.ones(30));q.fill(out);self.assertTrue(np.all(out==1))
        q.clear();q.fill(out);self.assertFalse(out.any())
        for _ in range(10):
            q.push(np.full(80,.25,dtype=np.float32))
            out=np.empty((80,2),dtype=np.float32);q.fill(out)
            np.testing.assert_array_equal(out,.25)

    def test_overflow_discards_old_speech(self):
        q=LiveBuffer(1000)
        q.push(np.full(200,.1,dtype=np.float32))
        q.push(np.full(100,.9,dtype=np.float32))
        self.assertEqual(q.overflows,1)
        self.assertEqual(q.count,60)
        out=np.zeros((60,2),dtype=np.float32);q.fill(out)
        np.testing.assert_allclose(out,.9)


class CertificateTests(unittest.TestCase):
    def test_unique_roots_profile_and_ip_renewal(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=prepare(Path(tmp)/'a','192.168.1.20')
            second=prepare(Path(tmp)/'a','192.168.1.21')
            other=prepare(Path(tmp)/'b','192.168.1.20')
            self.assertEqual(first['fingerprint'],second['fingerprint'])
            self.assertNotEqual(first['fingerprint'],other['fingerprint'])
            leaf=x509.load_pem_x509_certificate(second['cert'].read_bytes())
            self.assertEqual(leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
                .value.get_values_for_type(x509.IPAddress),[ipaddress.ip_address('192.168.1.21')])
            profile=plistlib.loads(second['profile'])
            self.assertEqual(len(profile['PayloadContent']),1)
            self.assertEqual(profile['PayloadContent'][0]['PayloadType'],'com.apple.security.root')


class FakeSink:
    def __init__(self):self.packets=[];self.rate=None;self.clear_count=0
    def begin(self,rate):self.rate=rate;self.clear()
    def feed(self,data):self.packets.append(data)
    def clear(self):self.clear_count+=1;self.packets.clear()


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sink=FakeSink()
        self.mic=MicServer('127.0.0.1','unused',self.sink)
        self.server=TestServer(self.mic.make_app())
        await self.server.start_server()
        self.client=ClientSession()

    async def asyncTearDown(self):
        await self.client.close();await self.server.close()

    async def connect(self,token=None,rate=48000):
        ws=await self.client.ws_connect(self.server.make_url('/audio'),origin='https://127.0.0.1:8765')
        await ws.send_json({'token':self.mic.token if token is None else token,'rate':rate})
        return ws

    async def test_auth_origin_and_rate_rejected(self):
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect(self.server.make_url('/audio'),origin='https://unrelated.invalid')
        for token,rate in [('wrong',48000),(self.mic.token,96000)]:
            ws=await self.connect(token,rate)
            self.assertEqual((await ws.receive()).type,WSMsgType.CLOSE)
        self.assertIsNone(self.sink.rate)

    async def test_live_pcm_single_client_disconnect_and_reconnect(self):
        ws=await self.connect();self.assertEqual((await ws.receive_json())['type'],'ready')
        second=await self.connect();self.assertEqual((await second.receive()).type,WSMsgType.CLOSE)
        packet=np.array([1,-32768,32767,0],dtype='<i2').tobytes()
        await ws.send_bytes(packet)
        # Poll a concrete network outcome with a bounded loop, not an arbitrary long sleep.
        for _ in range(100):
            if self.sink.packets:break
            await asyncio.sleep(.005)
        self.assertEqual(self.sink.packets,[packet])
        await ws.close()
        for _ in range(100):
            if self.mic.connection is None:break
            await asyncio.sleep(.005)
        self.assertEqual(self.sink.packets,[])
        third=await self.connect(rate=44100);self.assertEqual((await third.receive_json())['type'],'ready')
        self.assertEqual(self.sink.rate,44100)
        await third.close()

    async def test_malformed_pcm_closes_session(self):
        ws=await self.connect();await ws.receive_json()
        await ws.send_bytes(b'\x01')
        self.assertEqual((await ws.receive()).type,WSMsgType.CLOSE)

    async def test_no_audio_timeout(self):
        ws=await self.connect();await ws.receive_json()
        msg=await asyncio.wait_for(ws.receive(),timeout=5)
        self.assertEqual(msg.type,WSMsgType.CLOSE)


class TLSLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_tls_profile_access_and_restart(self):
        def free_port():
            with socket.socket() as s:
                s.bind(('127.0.0.1',0));return s.getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            port,setup=free_port(),free_port()
            previous_token = None
            for _ in range(2):
                sink=FakeSink()
                mic=MicServer('127.0.0.1',tmp,sink,https_port=port,setup_port=setup)
                mic.start()
                await asyncio.wait_for(asyncio.to_thread(mic.ready.wait),timeout=10)
                self.assertIsNone(mic.error)
                if previous_token is not None:self.assertEqual(mic.token,previous_token)
                previous_token=mic.token
                try:
                    context=ssl.create_default_context(cafile=str(Path(tmp)/'root.pem'))
                    async with ClientSession() as client:
                        async with client.get(mic.url.split('#')[0],ssl=context) as response:
                            self.assertEqual(response.status,200)
                            self.assertIn('PhoneMic',await response.text())
                        async with client.get(mic.setup_url+'certificate.mobileconfig') as response:
                            self.assertEqual(response.status,200)
                            self.assertEqual(plistlib.loads(await response.read())['PayloadType'],'Configuration')
                        async with client.get(f'http://127.0.0.1:{setup}/root-key.pem') as response:
                            self.assertEqual(response.status,404)
                        async with client.get(f'https://127.0.0.1:{port}/../certificates/root-key.pem',ssl=context) as response:
                            self.assertEqual(response.status,404)
                finally:
                    await asyncio.to_thread(mic.stop)
                self.assertFalse(mic.thread.is_alive())




class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sink=FakeSink()
        self.mic=MicServer('127.0.0.1','unused',self.sink)
        self.server=TestServer(self.mic.make_app());await self.server.start_server()
        self.client=ClientSession()
    async def asyncTearDown(self):
        await self.client.close();await self.server.close()
    async def connect(self, client_id='phone-identity-12345'):
        ws=await self.client.ws_connect(self.server.make_url('/audio'),origin='https://127.0.0.1:8765')
        await ws.send_json({'token':self.mic.token,'rate':48000,'protocol':2,'client_id':client_id})
        return ws
    async def test_same_phone_replaces_stale_socket_without_clearing_new_owner(self):
        from session_protocol import HEADER
        first=await self.connect();await first.receive_json()
        second=await self.connect();self.assertEqual((await second.receive_json())['type'],'ready')
        self.assertEqual((await first.receive()).data,4001)
        await second.send_bytes(HEADER.pack(b'PM02',1,1000.0)+b'\x01\x00'*960)
        ack=await second.receive_json();self.assertEqual(ack,{'type':'ack','seq':1})
        self.assertEqual(len(self.sink.packets),1)
        self.assertIsNotNone(self.mic.connection)
        third=await self.connect('different-phone-id-678')
        self.assertEqual((await third.receive()).data,4003)
        self.assertEqual(len(self.sink.packets),1)
        await second.close()
    async def test_duplicate_and_stale_packets_are_never_forwarded(self):
        from session_protocol import HEADER
        for stale in [False, True]:
            ws=await self.connect();await ws.receive_json()
            await ws.send_bytes(HEADER.pack(b'PM02',1,1000.0)+b'\x01\x00'*960)
            await ws.receive_json()
            if stale:await asyncio.sleep(.25)
            count=self.sink.clear_count
            await ws.send_bytes(HEADER.pack(b'PM02',2 if stale else 1,1000.0)+b'\x02\x00'*960)
            response=await ws.receive()
            self.assertEqual(response.type,WSMsgType.CLOSE)
            self.assertEqual(response.data,4002 if stale else 1008)
            for _ in range(100):
                if self.mic.connection is None:break
                await asyncio.sleep(.005)
            self.assertEqual(self.sink.packets,[])
            self.assertGreater(self.sink.clear_count,count)

class FreshnessTests(unittest.TestCase):
    def test_sleep_discards_pre_sleep_buffer(self):
        from unittest.mock import patch
        q=LiveBuffer(1000)
        with patch('audio_engine.time.monotonic',return_value=100):q.push(np.ones(100))
        out=np.ones((80,2),dtype=np.float32)
        with patch('audio_engine.time.monotonic',return_value=110):q.fill(out)
        self.assertFalse(out.any());self.assertEqual(q.count,0)
        with patch('audio_engine.time.monotonic',return_value=120):q.push(np.ones(100))
        with patch('audio_engine.time.monotonic',return_value=130):
            q.push(np.full(80,.25));q.fill(out)
        np.testing.assert_array_equal(out,.25)
    def test_wire_vector_matches_native_and_browser(self):
        from session_protocol import HEADER,FrameWindow
        packet=HEADER.pack(b'PM02',1,1000.0)+b'\x00\x80\xff\x7f'
        self.assertEqual(packet.hex(),'504d3032010000000000000000408f400080ff7f')
        self.assertEqual(FrameWindow().accept(packet,100),packet[16:])
    def test_nonfinite_and_regressing_timestamps_rejected(self):
        from session_protocol import HEADER,FrameWindow
        for stamp in [float('nan'),float('inf'),-1]:
            with self.assertRaises(ValueError):FrameWindow().accept(HEADER.pack(b'PM02',1,stamp)+b'00',1)
        window=FrameWindow();window.accept(HEADER.pack(b'PM02',1,1000)+b'00',1)
        with self.assertRaises(ValueError):window.accept(HEADER.pack(b'PM02',2,999)+b'00',2)

if __name__=='__main__':unittest.main()
