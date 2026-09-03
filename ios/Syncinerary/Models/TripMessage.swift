import Foundation

struct TripMessage: Codable, Sendable, Identifiable, Hashable {
    let id: UUID
    let tripID: UUID
    let travelerID: UUID?
    let authorName: String?
    let body: String
    let kind: String
    let linkAttachmentID: UUID?
    let link: MessageLink?
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case tripID = "trip_id"
        case travelerID = "traveler_id"
        case authorName = "author_name"
        case body
        case kind
        case linkAttachmentID = "link_attachment_id"
        case link
        case createdAt = "created_at"
    }

    /// A link the gather actually took. The thread is the only place the group
    /// can see what the agent got from their conversation.
    var becameACard: Bool { linkAttachmentID != nil }

    /// Dates cross the wire as strings everywhere in this app, so the parsing
    /// is local. FastAPI includes fractional seconds, which the plain
    /// `.withInternetDateTime` option rejects.
    var sentAt: Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = formatter.date(from: createdAt) { return parsed }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: createdAt)
    }
}

struct PostMessageRequest: Codable, Sendable {
    let body: String
}
