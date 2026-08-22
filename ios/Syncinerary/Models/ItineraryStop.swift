import Foundation

struct ItineraryStop: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    let candidateID: UUID
    let name: String
    let area: String?
    let startTime: String
    let endTime: String
    let transitFromPrevMin: Int
    let transitFromPrevMode: String?
}
