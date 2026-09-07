import Foundation
import SiteKit
import Yams

/// Minimal `SiteConfig.yaml` fragment for decoding the custom `apps:` block.
/// SiteKit's own `SiteConfig` decoder ignores unknown keys, so the rating
/// figures are re-read here independently (same approach as `LandingPageRenderer`).
private struct RatingsConfigFragment: Decodable {
   struct Localization: Decodable {
      let defaultLanguage: String?
      let languages: [String]?
   }

   let apps: AppRatings?
   let localization: Localization?
}

/// Replace `{{RATINGS_*}}` tokens in emitted HTML with live figures derived
/// from the `apps:` rating block in `SiteConfig.yaml`. This gives the About
/// and Reviews pages a single source of truth: refresh the counts in
/// `SiteConfig.yaml` and every page picks them up on the next build.
///
/// Numbers are formatted per locale by `LocaleNumber`, the same table the
/// landing-page trust line uses - so `/it/` reads `73.500`, `/fr/` `73 500`
/// and `/ar/` `٧٣٬٥٠٠`, and a page can never print `72.000` in its hero and
/// `73,500` in its body. The locale is the first path component under the
/// output root when that component is a configured language.
///
/// Tokens:
/// - `{{RATINGS_TOTAL}}` - sum of every app's count, floored to the nearest 500
/// - `{{RATINGS_AVG}}` - count-weighted mean rating, one decimal
/// - `{{RATINGS_TOOLS_IOS_COUNT}}` / `{{RATINGS_TOOLS_IOS_VALUE}}`
/// - `{{RATINGS_TOOLS_ANDROID_COUNT}}` / `{{RATINGS_TOOLS_ANDROID_VALUE}}`
/// - `{{RATINGS_BUSINESS_CARD_COUNT}}` / `{{RATINGS_BUSINESS_CARD_VALUE}}`
struct RatingsCountProcessor: OutputProcessor {
   func process(outputDirectory: URL, projectDirectory: URL, themeConfig: ThemeConfig?) throws {
      let configPath = projectDirectory.appendingPathComponent("SiteConfig.yaml")
      guard let yaml = try? String(contentsOf: configPath, encoding: .utf8),
            let fragment = try? YAMLDecoder().decode(RatingsConfigFragment.self, from: yaml),
            let ratings = fragment.apps,
            let toolsIOS = ratings.toolsIOS,
            let toolsAndroid = ratings.toolsAndroid,
            let businessCard = ratings.businessCardIOS
      else { return }

      let defaultLanguage = fragment.localization?.defaultLanguage ?? "en"
      let languages = Set(fragment.localization?.languages ?? [])

      let apps = [toolsIOS, toolsAndroid, businessCard]
      let totalCount = apps.reduce(0) { $0 + $1.ratingCount }
      guard totalCount > 0 else { return }
      let totalFloored = (totalCount / 500) * 500
      let weightedAverage = apps.reduce(0.0) { $0 + $1.ratingValue * Double($1.ratingCount) } / Double(totalCount)

      let fileManager = FileManager.default
      guard let enumerator = fileManager.enumerator(at: outputDirectory, includingPropertiesForKeys: nil) else { return }

      for case let url as URL in enumerator where url.pathExtension == "html" {
         guard var html = try? String(contentsOf: url, encoding: .utf8), html.contains("{{RATINGS_") else { continue }

         let locale = Self.locale(of: url, under: outputDirectory, languages: languages, default: defaultLanguage)
         let replacements: [String: String] = [
            "{{RATINGS_TOTAL}}": LocaleNumber.integer(totalFloored, locale: locale),
            "{{RATINGS_AVG}}": LocaleNumber.decimal(weightedAverage, places: 1, locale: locale),
            "{{RATINGS_TOOLS_IOS_COUNT}}": LocaleNumber.integer(toolsIOS.ratingCount, locale: locale),
            "{{RATINGS_TOOLS_IOS_VALUE}}": LocaleNumber.decimal(toolsIOS.ratingValue, places: 2, locale: locale),
            "{{RATINGS_TOOLS_ANDROID_COUNT}}": LocaleNumber.integer(toolsAndroid.ratingCount, locale: locale),
            "{{RATINGS_TOOLS_ANDROID_VALUE}}": LocaleNumber.decimal(toolsAndroid.ratingValue, places: 2, locale: locale),
            "{{RATINGS_BUSINESS_CARD_COUNT}}": LocaleNumber.integer(businessCard.ratingCount, locale: locale),
            "{{RATINGS_BUSINESS_CARD_VALUE}}": LocaleNumber.decimal(businessCard.ratingValue, places: 2, locale: locale),
         ]
         for (token, value) in replacements {
            html = html.replacingOccurrences(of: token, with: value)
         }
         try? html.write(to: url, atomically: true, encoding: .utf8)
      }
   }

   /// The locale a built page belongs to: the first path component under the
   /// output root when it names a configured language (`_Site/it/about/` ->
   /// `it`), the default language otherwise. Matching on the path component
   /// rather than `path.contains("/de/")` keeps a slug like `/blog/de-mystified/`
   /// from being mistaken for a locale directory.
   private static func locale(
      of url: URL,
      under outputDirectory: URL,
      languages: Set<String>,
      default defaultLanguage: String
   ) -> String {
      let root = outputDirectory.standardizedFileURL.pathComponents
      let components = url.standardizedFileURL.pathComponents
      guard components.count > root.count else { return defaultLanguage }
      let candidate = components[root.count]
      return languages.contains(candidate) ? candidate : defaultLanguage
   }
}
