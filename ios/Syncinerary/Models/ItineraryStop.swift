import Foundation

struct ItineraryStop: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    var timeRange: String {
        "\(startTime.prefix(5)) to \(endTime.prefix(5))"
    }

    var transitLabel: String {
        transitFromPrevMode ?? "travel"
    }

    let candidateID: UUID
    let name: String
    let area: String?
    let startTime: String
    let endTime: String
    let transitFromPrevMin: Int
    let transitFromPrevMode: String?
}
