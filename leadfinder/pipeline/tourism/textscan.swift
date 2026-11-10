import Vision
import AppKit
// usage: textscan <file>...   prints: file<TAB>chars<TAB>area-fraction
for path in CommandLine.arguments.dropFirst() {
  guard let img = NSImage(contentsOfFile: path), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("\(path)\t-1\t0"); continue }
  let req = VNRecognizeTextRequest()
  req.recognitionLevel = .fast
  req.usesLanguageCorrection = false
  try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
  var chars = 0; var area = 0.0
  for o in req.results ?? [] {
    if let t = o.topCandidates(1).first, t.confidence > 0.4 { chars += t.string.count; area += Double(o.boundingBox.width * o.boundingBox.height) }
  }
  print("\(path)\t\(chars)\t\(String(format: "%.3f", area))")
}
