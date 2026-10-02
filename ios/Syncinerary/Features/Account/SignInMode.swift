import Foundation

enum SignInMode {
    case signIn, register, forgot, reset

    var title: String {
        switch self {
        case .signIn: String(localized: "Welcome back.")
        case .register: String(localized: "Meet you there.")
        case .forgot: String(localized: "Forgot your password?")
        case .reset: String(localized: "A fresh start.")
        }
    }

    var action: String {
        switch self {
        case .signIn: String(localized: "Sign in")
        case .register: String(localized: "Create account")
        case .forgot: String(localized: "Send reset code")
        case .reset: String(localized: "Save new password")
        }
    }
}
