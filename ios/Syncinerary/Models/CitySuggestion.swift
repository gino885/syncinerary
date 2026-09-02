import Foundation

struct CitySuggestion: Codable, Identifiable, Sendable, Hashable {
    let placeID: String
    let name: String
    let subtitle: String?

    var id: String { placeID }

    enum CodingKeys: String, CodingKey {
        case placeID = "place_id"
        case name
        case subtitle
    }
}
