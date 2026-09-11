import Foundation

/// One post behind a card: the link, who posted it, and what it said.
struct SourcePost: Decodable, Hashable, Sendable {
    let platform: String
    let label: String
    let url: String
    let authorName: String?
    let highlight: String?

    var instagramReelURL: URL? {
        guard platform == "instagram", let parsed = URL(string: url),
              parsed.scheme == "https", parsed.user == nil, parsed.password == nil,
              parsed.port == nil,
              ["instagram.com", "www.instagram.com"].contains(parsed.host ?? "")
        else { return nil }
        let parts = parsed.path.split(separator: "/")
        guard parts.count == 2, parts[0] == "reel",
              !parts[1].isEmpty,
              parts[1].utf8.allSatisfy({
                  (65...90).contains($0) || (97...122).contains($0)
                  || (48...57).contains($0) || $0 == 45 || $0 == 95
              }) else { return nil }
        return URL(string: "https://www.instagram.com/reel/\(parts[1])/")
    }

    var linkURL: URL? {
        URL(string: url)
    }

    /// "TikTok by Travel Notes", or just the platform when the author is unknown.
    var title: String {
        if let authorName, !authorName.isEmpty {
            return String(localized: "\(label) by \(authorName)")
        }
        return label
    }

    enum CodingKeys: String, CodingKey {
        case platform
        case label
        case url
        case authorName = "author_name"
        case highlight
    }
}
