import Foundation

struct Account: Codable, Sendable, Identifiable, Hashable {
    let id: UUID
    let displayName: String
    let handle: String

    enum CodingKeys: String, CodingKey {
        case id
        case displayName = "display_name"
        case handle
    }
}
