import Foundation

/// One post behind a card: the link, who posted it, and what it said.
struct SourcePost: Decodable, Hashable, Sendable {
    let platform: String
    let label: String
    let url: String
    let authorName: String?
    let highlight: String?

    var linkURL: URL? {
        URL(string: url)
    }

    /// "TikTok by Travel Notes", or just the platform when the author is unknown.
    var title: String {
        if let authorName, !authorName.isEmpty {
            return "\(label) by \(authorName)"
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
