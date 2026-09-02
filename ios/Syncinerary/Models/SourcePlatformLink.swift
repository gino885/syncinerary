import Foundation

/// The highest-ranked original post for one platform represented on a card.
struct SourcePlatformLink: Hashable, Sendable {
    let platform: String
    let label: String
    let url: URL
}

extension SourcePost {
    /// Keeps the swipe card compact while exposing a real link for every
    /// platform. The detail sheet still lists every individual post.
    static func platformLinks(from posts: [SourcePost]) -> [SourcePlatformLink] {
        var seenPlatforms: Set<String> = []
        return posts.compactMap { post in
            guard
                seenPlatforms.insert(post.platform).inserted,
                let url = post.linkURL
            else {
                return nil
            }
            return SourcePlatformLink(
                platform: post.platform,
                label: post.label,
                url: url
            )
        }
    }
}
