import Foundation
import SiteKit

/// Rewrite render-blocking `<link rel="stylesheet">` tags for non-critical
/// CSS files into the `media="print"` swap pattern so they don't block
/// first paint.
///
/// SiteKit emits `<link rel="preload" as="style">` hints for every CSS in
/// `theme.yaml`'s `css:` list AND a follow-up `<link rel="stylesheet">`
/// later in `<head>`. The preload kicks off download early, but the sync
/// stylesheet still blocks render until parsed. For files that aren't
/// required above-the-fold (newsletter form, social links in footer, FAQ
/// accordions, etc.), we don't need that blocking.
///
/// The transform: `<link rel="stylesheet" href="…/foo.css">` becomes
/// `<link rel="stylesheet" href="…/foo.css" media="print" onload="this.media='all'">`
/// followed by a `<noscript>` fallback. The `media="print"` trick makes the
/// browser fetch the stylesheet without blocking screen rendering; the
/// `onload` flips it back to `all` once loaded.
///
/// Files left as synchronous (above-the-fold critical): `theme.css`,
/// `landing.css`. Everything else from `Theme/theme.yaml`'s `css:` list is
/// async-loaded.
struct CSSAsyncLoadProcessor: OutputProcessor {
   /// CSS basenames that should be async-loaded (not blocking first paint).
   /// Matches the non-critical entries in `Theme/theme.yaml`'s `css:` list.
   ///
   /// `nfc-reader` and `rtl` are page-scoped rather than merely below-the-fold:
   /// `nfc-reader.css` styles one page (`/online-nfc-reader/`) and `rtl.css` only
   /// applies under `[dir=rtl]` (the `/ar/` tree), yet both ship on every page.
   /// Async-loading them takes ~13.7 KB of render-blocking CSS off the other ~727.
   private let nonCriticalBasenames = ["newsletter", "marketing", "social", "faq", "blog", "features", "nfc-reader", "rtl"]

   /// Stylesheets that are non-critical *in general* but critical on the pages
   /// they actually target, keyed by the path prefix where they must stay
   /// render-blocking.
   ///
   /// `rtl.css` on `/ar/` drives the mirrored layout, so deferring it would
   /// paint the page left-to-right and then flip it; `nfc-reader.css` styles the
   /// widget panels that are the whole point of `/online-nfc-reader/`. On every
   /// other page each matches nothing and can load late.
   private let criticalUnderPath: [String: String] = ["rtl": "/ar/", "nfc-reader": "/online-nfc-reader/"]

   func process(outputDirectory: URL, projectDirectory: URL, themeConfig: ThemeConfig?) throws {
      let fileManager = FileManager.default
      guard let enumerator = fileManager.enumerator(at: outputDirectory, includingPropertiesForKeys: nil) else { return }

      for case let url as URL in enumerator where url.pathExtension == "html" {
         guard var html = try? String(contentsOf: url, encoding: .utf8) else { continue }
         var changed = false

         for basename in self.nonCriticalBasenames {
            // Keep this sheet synchronous on the pages it actually styles.
            if let prefix = self.criticalUnderPath[basename], url.path.contains(prefix) { continue }
            // Match `<link rel="stylesheet" href="...css/<basename>.css?v=...">` (with optional self-close).
            // SiteKit emits these without `media` attrs today; if a `media` attr is already present we skip.
            let pattern = #"<link rel="stylesheet" href="([^"]*/"# + basename + #"\.css(?:\?[^"]*)?)"\s*/?>"#
            guard let regex = try? NSRegularExpression(pattern: pattern) else { continue }
            let range = NSRange(html.startIndex..., in: html)
            let matches = regex.matches(in: html, range: range)
            guard !matches.isEmpty else { continue }

            // Replace from last match to first so earlier ranges stay valid.
            for match in matches.reversed() {
               guard let fullRange = Range(match.range, in: html),
                     let hrefRange = Range(match.range(at: 1), in: html) else { continue }
               let href = String(html[hrefRange])
               let replacement = #"<link rel="stylesheet" href="\#(href)" media="print" onload="this.media='all'"/><noscript><link rel="stylesheet" href="\#(href)"/></noscript>"#
               html.replaceSubrange(fullRange, with: replacement)
               changed = true
            }
         }

         if changed {
            try? html.write(to: url, atomically: true, encoding: .utf8)
         }
      }
   }
}
