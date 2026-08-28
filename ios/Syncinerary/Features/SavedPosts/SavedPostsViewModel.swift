import Foundation
import Observation

@MainActor
@Observable
final class SavedPostsViewModel {
    let session: TripSession

    var postURL = ""
    var placeName = ""
    var attachments: [SourceAttachmentResponse] = []
    var isSubmitting = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    var canAttach: Bool {
        guard !isSubmitting else { return false }
        let trimmed = postURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), let scheme = url.scheme else { return false }
        return scheme == "https" || scheme == "http"
    }

    func attach() async {
        guard canAttach else { return }
        isSubmitting = true
        defer { isSubmitting = false }

        do {
            let attachment = try await apiClient.attachLink(
                tripID: session.trip.id,
                request: AttachmentLinkRequest(
                    travelerID: session.travelerID,
                    url: postURL.trimmingCharacters(in: .whitespacesAndNewlines),
                    placeName: optionalText(placeName)
                )
            )
            if let index = attachments.firstIndex(where: { $0.id == attachment.id }) {
                attachments[index] = attachment
            } else {
                attachments.append(attachment)
            }
            if attachment.status == "ready" {
                postURL = ""
                placeName = ""
            }
        } catch {
            errorMessage = error.localizedDescription
            isShowingError = true
        }
    }

    private func optionalText(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
