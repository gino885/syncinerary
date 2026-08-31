import Foundation

struct DelegateBadge: Decodable, Sendable {
    let type: String
    let text: String
    let reasoning: String
}
