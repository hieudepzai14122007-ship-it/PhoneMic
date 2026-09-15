import SwiftUI

@main
struct PhoneMicApp: App {
    @StateObject private var mic = MicSession()
    var body: some Scene { WindowGroup { HomeView(mic: mic) } }
}

struct HomeView: View {
    @ObservedObject var mic: MicSession
    @State private var scanner = false
    @State private var manual = false
    @State private var link = ""
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text("Your iPhone. Your PC microphone.").font(.largeTitle.bold())
                    Label(mic.laptop, systemImage: "laptopcomputer").foregroundStyle(.secondary)
                    VStack(spacing: 18) {
                        Image(systemName: mic.muted ? "mic.slash.fill" : "mic.fill").font(.system(size: 44)).foregroundStyle(.mint)
                        Text(mic.status).font(.title2.bold()).multilineTextAlignment(.center)
                        ProgressView(value: Double(mic.level)).tint(.mint)
                        Text(mic.detail).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        Button(mic.active ? "Stop microphone" : "Start microphone") {
                            if mic.active { mic.stop() } else { mic.start() }
                        }.buttonStyle(.borderedProminent).tint(.teal).controlSize(.large)
                        Button(mic.muted ? "Unmute" : "Mute") { mic.toggleMute() }
                            .buttonStyle(.bordered).disabled(!mic.active)
                    }.padding(24).frame(maxWidth: .infinity).background(.thinMaterial, in: RoundedRectangle(cornerRadius: 24))
                    Button { scanner = true } label: { Label("Scan Native iPhone QR", systemImage: "qrcode.viewfinder") }.disabled(mic.active)
                    Button("Paste pairing link") { manual = true }.disabled(mic.active)
                    Text("Reconnect retries last up to 2 minutes. Audio during a network outage is discarded. Calls may require you to tap Start again. Stop always cancels retries.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("Windows: select CABLE Output as your microphone. This is an unverified native prototype; test lock-screen and interruption behavior on your iPhone before relying on it.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Button("Forget this laptop", role: .destructive) { mic.forget() }.disabled(mic.active)
                }.padding(24)
            }.navigationTitle("PhoneMic 0.2")
            .sheet(isPresented: $scanner) {
                QRScanner { value in scanner = false;mic.pair(link: value) }
            }
            .alert("Pair laptop", isPresented: $manual) {
                TextField("phonemic://pair?…", text: $link).textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("Pair") { mic.pair(link: link);link = "" }
                Button("Cancel", role: .cancel) { link = "" }
            } message: { Text("Paste the Native iPhone link from your Windows receiver.") }
        }
    }
}
