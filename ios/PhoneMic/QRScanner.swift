import SwiftUI
import AVFoundation

struct QRScanner: UIViewControllerRepresentable {
    let found: (String) -> Void
    func makeUIViewController(context: Context) -> ScannerController { ScannerController(found: found) }
    func updateUIViewController(_ controller: ScannerController, context: Context) {}
    static func dismantleUIViewController(_ controller: ScannerController, coordinator: ()) { controller.stop() }
}

final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    let capture = AVCaptureSession()
    let cameraQueue = DispatchQueue(label: "PhoneMic.camera")
    let found: (String) -> Void
    var preview: AVCaptureVideoPreviewLayer?
    var emitted = false
    // Camera queue owns this flag so dismissing during permission cannot reopen it.
    var cancelled = false
    init(found: @escaping (String) -> Void) { self.found = found;super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
    override func viewDidLoad() {
        super.viewDidLoad();view.backgroundColor = .black
        AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
            guard let self = self else { return }
            if granted { self.configure() }
            else { DispatchQueue.main.async { self.showError("Camera permission is needed. Close this sheet and use Paste pairing link instead.") } }
        }
    }
    func configure() {
        cameraQueue.async {
            guard !self.cancelled,
                  let camera = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: camera), self.capture.canAddInput(input) else { return }
            self.capture.addInput(input)
            let output = AVCaptureMetadataOutput()
            guard self.capture.canAddOutput(output) else { return }
            self.capture.addOutput(output);output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]
            DispatchQueue.main.async {
                let preview = AVCaptureVideoPreviewLayer(session: self.capture)
                preview.videoGravity = .resizeAspectFill;preview.frame = self.view.bounds
                self.view.layer.addSublayer(preview);self.preview = preview
            }
            self.capture.startRunning()
        }
    }
    override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews();preview?.frame = view.bounds }
    func stop() { cameraQueue.async { self.cancelled = true;self.capture.stopRunning() } }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !emitted, let qr = metadataObjects.first as? AVMetadataMachineReadableCodeObject, let text = qr.stringValue else { return }
        emitted = true;stop();found(text)
    }
    func showError(_ message: String) {
        let label = UILabel();label.text = message;label.textColor = .white;label.numberOfLines = 0;label.textAlignment = .center
        label.frame = view.bounds.insetBy(dx: 24, dy: 100);label.autoresizingMask = [.flexibleWidth, .flexibleHeight];view.addSubview(label)
    }
}
