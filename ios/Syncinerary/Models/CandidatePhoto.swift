import Foundation

struct CandidatePhoto: Decodable, Sendable {
    let provider: String
    let photoURL: URL
    let widthPixels: Int?
    let heightPixels: Int?
    let attributions: [PhotoAttribution]

    enum CodingKeys: String, CodingKey {
        case provider
        case photoURL = "photo_url"
        case widthPixels = "width_px"
        case heightPixels = "height_px"
        case attributions
    }
}
