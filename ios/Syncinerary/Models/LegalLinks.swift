import Foundation

enum LegalLinks {
    static let privacyPolicy = url(for: "SyncPrivacyPolicyURL")
    static let support = url(for: "SyncSupportURL")

    private static func url(for key: String) -> URL? {
        guard
            let value = Bundle.main.object(forInfoDictionaryKey: key) as? String,
            let url = URL(string: value),
            url.scheme == "https"
        else { return nil }
        return url
    }
}
