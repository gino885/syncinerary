import Foundation

enum AppLanguage {
    /// The localization the user chose for this app, not their region format.
    static var currentOutputLocaleIdentifier: String {
        outputLocaleIdentifier(for: Bundle.main.preferredLocalizations.first)
    }

    static func outputLocaleIdentifier(for identifier: String?) -> String {
        guard let identifier else { return "en" }
        let normalized = identifier.replacing("_", with: "-").lowercased()

        if normalized.hasPrefix("zh-hans")
            || normalized.hasPrefix("zh-cn")
            || normalized.hasPrefix("zh-sg") {
            return "zh-Hans"
        }
        if normalized.hasPrefix("zh") {
            // Traditional Chinese is the Chinese localization currently
            // shipped by the app, including for a bare `zh` preference.
            return "zh-Hant"
        }
        if normalized.hasPrefix("ja") {
            return "ja"
        }
        return "en"
    }
}
