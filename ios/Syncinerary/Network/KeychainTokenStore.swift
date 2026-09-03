import Foundation
import Security

/// Stores the session token in the Keychain.
///
/// `UserDefaults` holds the API base URL and the resume trip id, which are
/// preferences. A bearer token is a credential: it belongs somewhere that is
/// encrypted at rest and not included in an unencrypted device backup, which
/// is what `ThisDeviceOnly` buys.
enum KeychainTokenStore {
    private static let service = "com.syncinerary.session"
    private static let account = "bearer-token"

    static func save(_ token: String) {
        guard let data = token.data(using: .utf8) else { return }
        // Delete first: SecItemAdd fails with errSecDuplicateItem otherwise,
        // and signing in again has to replace the old token.
        delete()
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    static func load() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data
        else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    static func delete() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
