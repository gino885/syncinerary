import Foundation

/// `syncinerary://invite/CODE`.
///
/// The typed code stays as a fallback, because a code read aloud over dinner
/// still has to work, but a tapped link is what the research says decides
/// whether the rest of the group actually turns up.
enum InviteLink {
    static let scheme = "syncinerary"

    static func url(for code: String) -> URL? {
        URL(string: "\(scheme)://invite/\(code)")
    }

    static func code(from url: URL) -> String? {
        guard url.scheme?.lowercased() == scheme else { return nil }
        // syncinerary://invite/CODE parses host as "invite" and the code as
        // the first path component.
        let parts = ([url.host] + url.pathComponents.map { Optional($0) })
            .compactMap { $0 }
            .filter { $0 != "/" }
        guard parts.first?.lowercased() == "invite", parts.count > 1 else { return nil }
        let code = parts[1].uppercased()
        return code.isEmpty ? nil : code
    }
}
