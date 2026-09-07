import Foundation

/// Locale-aware number formatting for the figures this site prints in prose -
/// store rating counts and averages.
///
/// Hand-rolled rather than `NumberFormatter`-based on purpose: the output is
/// baked into static HTML at build time, so it must be deterministic across
/// machines and CI images (Foundation's ICU data differs between macOS and the
/// Ubuntu runner, and `pt`/`ar` are exactly where it diverges). The table below
/// is the CLDR convention for each locale the site ships, and it is reviewable.
///
/// Arabic gets Eastern-Arabic (Arabic-Indic) digits plus U+066C / U+066B
/// separators, matching the numerals already hand-written throughout
/// `Content/Data/Landing.ar.yaml`. French uses U+202F (narrow no-break space).
enum LocaleNumber {
   private struct Style {
      let grouping: String
      let decimal: String
      /// Non-nil when the locale renders digits in a script other than Latin.
      let digits: [Character]?
   }

   private static let easternArabicDigits: [Character] = ["٠", "١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"]

   private static let styles: [String: Style] = [
      "en": Style(grouping: ",", decimal: ".", digits: nil),
      "de": Style(grouping: ".", decimal: ",", digits: nil),
      "ja": Style(grouping: ",", decimal: ".", digits: nil),
      "pt": Style(grouping: ".", decimal: ",", digits: nil),
      "zh": Style(grouping: ",", decimal: ".", digits: nil),
      "id": Style(grouping: ".", decimal: ",", digits: nil),
      "es": Style(grouping: ".", decimal: ",", digits: nil),
      "fr": Style(grouping: "\u{202F}", decimal: ",", digits: nil),
      "ar": Style(grouping: "\u{066C}", decimal: "\u{066B}", digits: easternArabicDigits),
      "it": Style(grouping: ".", decimal: ",", digits: nil),
      "tr": Style(grouping: ".", decimal: ",", digits: nil),
   ]

   private static func style(for locale: String) -> Style {
      self.styles[locale] ?? self.styles["en"]!
   }

   private static func transliterate(_ text: String, using digits: [Character]?) -> String {
      guard let digits else { return text }
      return String(text.map { character in
         guard let value = character.wholeNumberValue, (0...9).contains(value) else { return character }
         return digits[value]
      })
   }

   /// Groups digits in threes using the locale's separator, e.g. `70,660`
   /// (en), `70.660` (de), `70 660` (fr), `٧٠٬٦٦٠` (ar).
   static func integer(_ value: Int, locale: String) -> String {
      let style = self.style(for: locale)
      let digits = Array(String(abs(value)))
      var result = ""
      for (offset, digit) in digits.enumerated() {
         if offset != 0, (digits.count - offset).isMultiple(of: 3) { result += style.grouping }
         result.append(digit)
      }
      let signed = value < 0 ? "-" + result : result
      return self.transliterate(signed, using: style.digits)
   }

   /// Rounds to `places` decimals using the locale's decimal separator,
   /// e.g. `4.5` (en), `4,5` (de), `٤٫٥` (ar).
   static func decimal(_ value: Double, places: Int, locale: String) -> String {
      let style = self.style(for: locale)
      let rendered = String(format: "%.\(places)f", value)
         .replacingOccurrences(of: ".", with: style.decimal)
      return self.transliterate(rendered, using: style.digits)
   }
}
