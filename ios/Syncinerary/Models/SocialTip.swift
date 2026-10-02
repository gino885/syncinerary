import Foundation

struct SocialTip: Decodable, Sendable {
    let text: String
    let url: URL
    let source: String
    let kind: String
}
