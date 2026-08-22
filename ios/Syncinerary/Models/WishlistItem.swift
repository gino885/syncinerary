import Foundation

struct WishlistItem: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    let candidateID: UUID
    let name: String
    let reasonCode: String
    let reasonText: String
}
