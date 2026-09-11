import Foundation

enum CountryIdentifier {
    /// Converts a country name in any app-supported language to its stable
    /// ISO 3166-1 alpha-2 code. Unknown text is preserved so the provider can
    /// still resolve country spellings outside the shipped localizations.
    static func canonicalCode(for country: String) -> String {
        let trimmed = country.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = normalized(trimmed)
        return codeByLocalizedName[key] ?? trimmed
    }

    private static let supportedLocaleIdentifiers = [
        "en",
        "zh-Hant",
        "zh-Hans",
        "ja",
    ]

    private static let codeByLocalizedName: [String: String] = {
        var result: [String: String] = [:]
        let locales = supportedLocaleIdentifiers.map(Locale.init(identifier:))

        for region in Locale.Region.isoRegions where region.identifier.count == 2 {
            let code = region.identifier.uppercased()
            result[normalized(code)] = code
            for locale in locales {
                if let name = locale.localizedString(forRegionCode: code) {
                    result[normalized(name)] = code
                }
            }
        }
        return result
    }()

    private static func normalized(_ value: String) -> String {
        value
            .folding(
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive],
                locale: Locale(identifier: "en_US_POSIX")
            )
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
