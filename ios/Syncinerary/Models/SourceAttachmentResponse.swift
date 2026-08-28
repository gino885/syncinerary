import Foundation

struct SourceAttachmentResponse: Decodable, Identifiable, Sendable {
    let id: UUID
    let platform: String
    let inputType: String
    let status: String
    let originalURL: URL?
    let canonicalURL: URL?
    let hasScreenshot: Bool
    let submittedPlaceName: String?
    let candidateID: UUID?
    let contributor: AttachmentContributor

    enum CodingKeys: String, CodingKey {
        case id
        case platform
        case inputType = "input_type"
        case status
        case originalURL = "original_url"
        case canonicalURL = "canonical_url"
        case hasScreenshot = "has_screenshot"
        case submittedPlaceName = "submitted_place_name"
        case candidateID = "candidate_id"
        case contributor
    }
}
