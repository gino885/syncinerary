import Foundation
import Observation

@MainActor
@Observable
final class ManualItineraryViewModel {
    let session: TripSession
    let itinerary: ItineraryResponse
    var stops: [ItineraryDraftStop]
    var selectedDay: Int
    var isSubmitting = false
    var isSearching = false
    var errorMessage: String?
    var places: [ItineraryPlaceOption] = []
    var searchQuery = ""
    var searchedQuery = ""
    var link = ""
    var linkedPlaceName = ""
    private let apiClient: APIClient

    init(session: TripSession, itinerary: ItineraryResponse, day: Int = 0, apiClient: APIClient = .shared) {
        self.session = session
        self.itinerary = itinerary
        self.selectedDay = day
        self.apiClient = apiClient
        self.stops = itinerary.days.flatMap { day in
            day.stops.map { stop in
                ItineraryDraftStop(candidateID: stop.candidateID, name: stop.name, day: day.day,
                    startMinute: ItineraryDraftStop.minute(stop.startTime),
                    durationMinutes: ItineraryDraftStop.minute(stop.endTime) - ItineraryDraftStop.minute(stop.startTime),
                    fixed: stop.fixed == true || ["reservation", "paid_ticket", "flight", "check_in"].contains(stop.lockReason ?? ""))
            }
        }
    }

    var dayStops: [ItineraryDraftStop] {
        stops.filter { $0.day == selectedDay }.sorted { $0.startMinute < $1.startMinute }
    }
    var availablePlaces: [ItineraryPlaceOption] {
        places.filter { option in !stops.contains { $0.candidateID == option.candidateID } }
    }
    var valid: Bool {
        stops.allSatisfy { $0.startMinute >= 0 && $0.endMinute < 1440 && $0.durationMinutes > 0 }
    }

    func update(_ stop: ItineraryDraftStop) {
        guard let index = stops.firstIndex(where: { $0.id == stop.id }), !stops[index].fixed else { return }
        stops[index] = stop
    }

    func remove(_ stop: ItineraryDraftStop) {
        guard !stop.fixed else { return }
        stops.removeAll { $0.id == stop.id }
    }

    func move(from offsets: IndexSet, to destination: Int) {
        var ordered = dayStops
        guard !ordered.contains(where: \.fixed) else {
            errorMessage = String(localized: "This day contains a fixed reservation. Edit individual stop times instead.")
            return
        }
        let moving = offsets.sorted().map { ordered[$0] }
        let insertion = destination - offsets.filter { $0 < destination }.count
        for index in offsets.sorted(by: >) { ordered.remove(at: index) }
        ordered.insert(contentsOf: moving, at: insertion)
        var start = dayStops.first?.startMinute ?? 540
        for var stop in ordered {
            stop.startMinute = start
            update(stop)
            start = stop.endMinute + 30
        }
    }

    func search(savedOnly: Bool = false) async {
        guard !isSearching else { return }
        isSearching = true
        errorMessage = nil
        defer { isSearching = false }
        let query = savedOnly ? "" : searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            places = try await apiClient.itineraryPlaces(tripID: session.trip.id,
                travelerID: session.travelerID, day: selectedDay, query: query)
            searchedQuery = query
        } catch { errorMessage = error.localizedDescription }
    }

    func select(_ option: ItineraryPlaceOption) async -> ItineraryDraftStop? {
        guard !isSearching else { return nil }
        isSearching = true
        errorMessage = nil
        defer { isSearching = false }
        do {
            let selected: ItineraryPlaceOption
            if option.candidateID != nil { selected = option }
            else {
                guard let placeID = option.placeID else { return nil }
                selected = try await apiClient.selectItineraryPlace(tripID: session.trip.id,
                    request: SelectItineraryPlaceRequest(travelerID: session.travelerID,
                        day: selectedDay, query: searchedQuery, placeID: placeID))
            }
            guard let id = selected.candidateID, !stops.contains(where: { $0.id == id }) else { return nil }
            return ItineraryDraftStop(candidateID: id, name: selected.name, day: selectedDay,
                startMinute: min(dayStops.last.map { $0.endMinute + 30 } ?? 540, 1200),
                durationMinutes: max(30, ((selected.durationMinutes + 29) / 30) * 30), fixed: false)
        } catch { errorMessage = error.localizedDescription; return nil }
    }

    func readLink() async {
        guard !isSearching else { return }
        isSearching = true
        errorMessage = nil
        defer { isSearching = false }
        do {
            let attachment = try await apiClient.attachLink(tripID: session.trip.id,
                request: AttachmentLinkRequest(travelerID: session.travelerID, url: link,
                    placeName: linkedPlaceName.isEmpty ? nil : linkedPlaceName))
            guard let id = attachment.candidateID else {
                errorMessage = String(localized: "Enter the place name and try the link again, or search for the place.")
                return
            }
            let saved = try await apiClient.itineraryPlaces(tripID: session.trip.id,
                travelerID: session.travelerID, day: selectedDay)
            places = saved.filter { $0.candidateID == id }
            if places.isEmpty { errorMessage = String(localized: "This place is not available on the selected city day.") }
        } catch { errorMessage = error.localizedDescription }
    }

    func add(_ stop: ItineraryDraftStop) {
        guard !stops.contains(where: { $0.id == stop.id }) else { return }
        stops.append(stop)
    }

    func preview(adjustDay: Bool = false) async -> ReplanProposalResponse? {
        guard !isSubmitting, valid else { return nil }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }
        do {
            return try await apiClient.previewItineraryEdit(tripID: session.trip.id,
                request: ManualItineraryRequest(travelerID: session.travelerID,
                    baseVersionID: itinerary.versionID, stops: stops,
                    adjustDays: adjustDay ? [selectedDay] : []))
        } catch { errorMessage = error.localizedDescription; return nil }
    }
}
