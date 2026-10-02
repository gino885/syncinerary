import Foundation
import Observation

@MainActor
@Observable
final class LodgingViewModel {
    let session: TripSession

    var hotelQuery = ""
    var hotelCity: String
    var hotelMatches: [HotelMatch] = []
    var isSearchingHotel = false
    var isSavingHotel = false
    var didSearchHotel = false
    private var searchedQuery = ""
    private var searchedCity = ""

    var options: [LodgingOption] = []
    var selectedID: UUID?
    var isLoading = false
    var isPlanning = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient
    private var hasLoaded = false

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.hotelCity = session.trip.cities.first ?? session.trip.destination
        self.apiClient = apiClient
    }

    func load() async {
        guard !hasLoaded else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            options = try await apiClient.lodgingOptions(tripID: session.trip.id)
            selectedID = options.first(where: { $0.isSelected == true })?.id ?? options.first?.id
            hasLoaded = true
        } catch {
            show(error)
        }
    }

    func clearHotelResults() {
        hotelMatches = []
        didSearchHotel = false
    }

    func searchHotels() async {
        guard !isSearchingHotel && !isSavingHotel else { return }
        isSearchingHotel = true
        hotelMatches = []
        didSearchHotel = false
        let query = hotelQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        let city = hotelCity
        defer { isSearchingHotel = false }
        do {
            let matches = try await apiClient.searchHotels(tripID: session.trip.id,
                travelerID: session.travelerID, city: city, query: query)
            guard hotelQuery.trimmingCharacters(in: .whitespacesAndNewlines) == query, hotelCity == city else { return }
            searchedQuery = query
            searchedCity = city
            hotelMatches = matches
            didSearchHotel = true
        } catch { show(error) }
    }

    func saveHotel(_ hotel: HotelMatch) async {
        guard !isSavingHotel, hotelMatches.contains(where: { $0.id == hotel.id }) else { return }
        isSavingHotel = true
        defer { isSavingHotel = false }
        do {
            let saved = try await apiClient.saveBookedHotel(tripID: session.trip.id,
                request: BookedHotelRequest(travelerID: session.travelerID, city: searchedCity,
                                           query: searchedQuery, placeID: hotel.placeID))
            options = [saved] + options.filter { $0.id != saved.id }.map { option in
                var option = option
                option.isSelected = false
                option.isBooked = false
                return option
            }
            selectedID = saved.id
            clearHotelResults()
            hotelQuery = ""
        } catch { show(error) }
    }

    func choose(_ option: LodgingOption) {
        selectedID = option.id
    }

    func selectAndPlan() async -> Bool {
        guard let selectedID, !isPlanning else { return false }
        isPlanning = true
        defer { isPlanning = false }
        do {
            _ = try await apiClient.selectLodging(
                tripID: session.trip.id,
                request: LodgingSelectionRequest(
                    travelerID: session.travelerID,
                    candidateID: selectedID
                )
            )
            _ = try await apiClient.plan(
                tripID: session.trip.id,
                request: session.planRequest
            )
            return true
        } catch {
            show(error)
            return false
        }
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        isShowingError = true
    }
}
