import Foundation
import Observation

@MainActor @Observable
final class ChecklistViewModel {
    let session: TripSession
    var items: [ChecklistItem] = []
    var isBusy = false
    var errorMessage: String?
    private let api: APIClient

    init(session: TripSession, api: APIClient = .shared) {
        self.session = session
        self.api = api
    }

    func load() async {
        guard !isBusy else { return }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }
        do {
            items = try await api.prepareChecklist(tripID: session.trip.id, travelerID: session.travelerID)
        } catch { errorMessage = error.localizedDescription }
    }

    func save(_ item: ChecklistItem?, title: String, notes: String, completed: Bool = false) async -> Bool {
        guard !isBusy else { return false }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }
        do {
            let request = ChecklistRequest(travelerID: session.travelerID,
                title: title.trimmingCharacters(in: .whitespacesAndNewlines), notes: notes,
                completed: completed, revision: item?.revision)
            let saved = try await api.saveChecklistItem(tripID: session.trip.id, itemID: item?.id, request: request)
            if let index = items.firstIndex(where: { $0.id == saved.id }) { items[index] = saved }
            else { items.append(saved) }
            return true
        } catch { errorMessage = error.localizedDescription; return false }
    }

    func toggle(_ item: ChecklistItem) async {
        _ = await save(item, title: item.title, notes: item.notes, completed: !item.completed)
    }

    func remove(_ item: ChecklistItem) async -> Bool {
        guard !isBusy else { return false }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }
        do {
            try await api.removeChecklistItem(tripID: session.trip.id, travelerID: session.travelerID, item: item)
            items.removeAll { $0.id == item.id }
            return true
        } catch { errorMessage = error.localizedDescription; return false }
    }
}
