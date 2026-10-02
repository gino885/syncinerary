import Foundation
import Observation

@MainActor @Observable
final class TripChatViewModel {
    private(set) var messages: [TripMessage] = []
    private(set) var session: TripSession?
    private(set) var isSending = false
    private(set) var errorMessage: String?
    var draft = ""
    private var isLoading = false
    private var revision = 0
    private let trip: TripListRow
    private let client: APIClient

    init(trip: TripListRow, client: APIClient = .shared) {
        self.trip = trip
        self.client = client
    }

    var canSend: Bool {
        !isSending && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func load() async {
        guard !isLoading && !isSending else { return }
        isLoading = true
        defer { isLoading = false }
        let loadingRevision = revision
        do {
            if session == nil {
                let summary = try await client.trip(tripID: trip.id)
                session = TripSession(trip: summary, travelerID: trip.travelerID, planRequest: .standard)
            }
            let loaded = try await client.messages(tripID: trip.id)
            // A refresh started before a send or repair must not overwrite it.
            guard loadingRevision == revision else { return }
            messages = loaded
        } catch is CancellationError {
        } catch {
            guard !Task.isCancelled, loadingRevision == revision else { return }
            errorMessage = String(localized: "Could not load the thread. Pull down to retry.")
        }
    }

    func send() async {
        guard canSend else { return }
        let submittedDraft = draft
        isSending = true
        revision += 1
        defer { isSending = false }
        do {
            let posted = try await client.postMessage(tripID: trip.id,
                body: submittedDraft.trimmingCharacters(in: .whitespacesAndNewlines))
            if !messages.contains(where: { $0.id == posted.id }) { messages.append(posted) }
            if draft == submittedDraft { draft = "" }
            errorMessage = nil
        } catch {
            errorMessage = String(localized: "Message not sent. Try again.")
        }
    }

    func name(_ message: TripMessage, as placeName: String) async {
        revision += 1
        do {
            let updated = try await client.namePlace(tripID: trip.id, messageID: message.id, placeName: placeName)
            revision += 1
            if let index = messages.firstIndex(where: { $0.id == updated.id }) { messages[index] = updated }
            errorMessage = nil
        } catch {
            errorMessage = String(localized: "Could not add that place.")
        }
    }

    func dismissError() { errorMessage = nil }
}
