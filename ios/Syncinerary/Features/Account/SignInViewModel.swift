import Foundation
import Observation

@MainActor @Observable
final class SignInViewModel {
    var mode = SignInMode.signIn
    var displayName = ""
    var email = ""
    var password = ""
    var confirmPassword = ""
    var code = ""
    private(set) var isWorking = false
    private(set) var errorMessage: String?
    private(set) var notice: String?
    private let client: APIClient

    init(client: APIClient = .shared) { self.client = client }
    var actionTitle: String { mode.action }
    var normalizedEmail: String { email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
    var needsCode: Bool { mode == .reset }
    var needsPassword: Bool { mode != .forgot }
    var createsPassword: Bool { mode == .register || mode == .reset }
    var canSubmit: Bool {
        let parts = normalizedEmail.split(separator: "@", omittingEmptySubsequences: false)
        guard parts.count == 2, !parts[0].isEmpty, parts[1].contains("."),
              !normalizedEmail.contains(where: { $0.isWhitespace }), normalizedEmail.count <= 254 else { return false }
        if mode == .register && (displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || displayName.count > 60) { return false }
        if needsPassword && (password.isEmpty || password.unicodeScalars.count > 128) { return false }
        if createsPassword && (password.unicodeScalars.count < 8 || password != confirmPassword) { return false }
        if needsCode && (code.count != 8 || !code.utf8.allSatisfy({ (48...57).contains($0) })) { return false }
        return !isWorking
    }

    func switchMode(_ mode: SignInMode) {
        guard !isWorking else { return }
        if mode == .register && self.mode != .register {
            email = ""
            displayName = ""
        }
        self.mode = mode
        password = ""; confirmPassword = ""; code = ""
        errorMessage = nil; notice = nil
    }

    func submit(accounts: AccountStore) async {
        guard canSubmit, !accounts.isWorking else { return }
        isWorking = true
        errorMessage = nil
        notice = nil
        defer { isWorking = false }
        do {
            switch mode {
            case .signIn:
                if await accounts.signIn(email: normalizedEmail, password: password) { clearSecrets() }
                else { errorMessage = accounts.errorMessage }
            case .register:
                if await accounts.register(email: normalizedEmail,
                                           displayName: displayName.trimmingCharacters(in: .whitespacesAndNewlines),
                                           password: password) { clearSecrets() }
                else { errorMessage = accounts.errorMessage }
            case .forgot:
                try await client.authAction("password/forgot", request: EmailAuthRequest(email: normalizedEmail))
                mode = .reset
            case .reset:
                try await client.authAction("password/reset", request: EmailAuthRequest(email: normalizedEmail, code: code, password: password))
                clearSecrets()
                mode = .signIn
                notice = String(localized: "Password updated. Sign in with your new password.")
            }
        } catch { errorMessage = AccountStore.message(for: error) }
    }

    func resend() async {
        guard !isWorking else { return }
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }
        do {
            let request = EmailAuthRequest(email: normalizedEmail)
            try await client.authAction("password/forgot", request: request)
            notice = String(localized: "If this email is eligible, a new code is on its way.")
        } catch { errorMessage = AccountStore.message(for: error) }
    }

    private func clearSecrets() { password = ""; confirmPassword = ""; code = "" }
}
