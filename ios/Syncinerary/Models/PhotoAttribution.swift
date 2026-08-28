import Foundation

struct PhotoAttribution: Decodable, Sendable {
    let displayName: String
    let uri: URL?
    let photoURI: URL?

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case uri
        case photoURI = "photo_uri"
    }
}
