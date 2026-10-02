import Foundation

struct HotelMatch: Decodable, Identifiable, Sendable {
    var id: String { placeID }
    let placeID: String
    let name: String
    let address: String?

    enum CodingKeys: String, CodingKey {
        case placeID = "place_id"
        case name, address
    }
}
