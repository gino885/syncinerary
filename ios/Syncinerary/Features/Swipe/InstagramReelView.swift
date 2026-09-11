import SwiftUI
import WebKit

/// Render Instagram's own public embed after the traveler asks to play it.
/// No media is extracted or copied into app storage.
struct InstagramReelView: UIViewRepresentable {
    let url: URL
    @Environment(\.openURL) private var openURL

    func makeCoordinator() -> Coordinator { Coordinator(open: { openURL($0) }) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        guard context.coordinator.loadedURL != url else { return }
        context.coordinator.loadedURL = url
        // url comes only from SourcePost.instagramReelURL's strict parser.
        view.loadHTMLString("""
            <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
            <body style="margin:0">
            <blockquote class="instagram-media" data-instgrm-permalink="\(url.absoluteString)"
                data-instgrm-version="14" style="margin:0;width:100%">
                <a href="\(url.absoluteString)">\(String(localized: "Open in Instagram"))</a>
            </blockquote>
            <script async src="https://www.instagram.com/embed.js"></script>
            </body></html>
            """, baseURL: nil)
    }

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.stopLoading()
        view.loadHTMLString("", baseURL: nil)
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate {
        var loadedURL: URL?
        let open: (URL) -> Void

        init(open: @escaping (URL) -> Void) { self.open = open }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            if action.navigationType == .linkActivated, let url = action.request.url {
                if url.scheme == "https" { open(url) }
                decisionHandler(.cancel)
                return
            }
            // Login and other top-level navigations stay in the system browser.
            if action.targetFrame?.isMainFrame != false,
               let url = action.request.url, url.scheme != "about" {
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
