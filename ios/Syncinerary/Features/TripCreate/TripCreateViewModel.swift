import Foundation
import Observation

@MainActor
@Observable
final class TripCreateViewModel {
    /// Both start empty on purpose: there is no default destination for the
    /// traveler to plan around by accident.
    var country = ""
    var cityQuery = ""
    var selectedCities: [CitySuggestion] = []
    var citySuggestions: [CitySuggestion] = []
    var citySearchMessage: String?
    var creatorName = ""
    var creatorHomeCity = ""
    var interestSelection = PreferenceSelection()
    var dietarySelection = PreferenceSelection()
    var startDate: Date
    var endDate: Date
    var dayStart: Date
    var dayEnd: Date
    var isSubmitting = false
    var isSearchingCities = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient

    init(apiClient: APIClient = .shared) {
        self.apiClient = apiClient
        let calendar = Calendar.current
        let start = calendar.date(byAdding: .day, value: 30, to: .now) ?? .now
        startDate = start
        endDate = calendar.date(byAdding: .day, value: 4, to: start) ?? start
        dayStart = calendar.date(bySettingHour: 8, minute: 0, second: 0, of: .now) ?? .now
        // 21:00 leaves room for dinner; the solver will not schedule past it.
        dayEnd = calendar.date(bySettingHour: 21, minute: 0, second: 0, of: .now) ?? .now
    }

    var cityNames: [String] { selectedCities.map(\.name) }

    var cityPlaceIDs: [String] { selectedCities.map(\.placeID) }

    var preferenceSummary: String {
        PreferenceSelection.tripSummary(
            interests: interestSelection,
            dietary: dietarySelection
        )
    }

    var trimmedCountry: String {
        country.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var canSubmit: Bool {
        !trimmedCountry.isEmpty
            && !cityNames.isEmpty
            && !creatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && endDate >= startDate
            && minuteOfDay(dayEnd) > minuteOfDay(dayStart)
            && !isSubmitting
    }

    var canSearchCities: Bool {
        !trimmedCountry.isEmpty
            && cityQuery.trimmingCharacters(in: .whitespacesAndNewlines).count >= 2
            && selectedCities.count < 4
            && !isSearchingCities
    }

    func adjustEndDate() {
        guard endDate < startDate else { return }
        endDate = Calendar.current.date(byAdding: .day, value: 4, to: startDate) ?? startDate
    }

    func countryChanged() {
        selectedCities = []
        citySuggestions = []
        citySearchMessage = nil
    }

    func searchCities() async {
        guard canSearchCities else { return }
        isSearchingCities = true
        citySearchMessage = nil
        defer { isSearchingCities = false }

        do {
            let results = try await apiClient.citySuggestions(
                country: trimmedCountry,
                query: cityQuery.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            let selectedIDs = Set(selectedCities.map(\.placeID))
            citySuggestions = results.filter { !selectedIDs.contains($0.placeID) }
            if citySuggestions.isEmpty {
                citySearchMessage = "No matching cities found. Try another spelling."
            }
        } catch {
            citySuggestions = []
            citySearchMessage = error.localizedDescription
        }
    }

    func selectCity(_ suggestion: CitySuggestion) {
        guard selectedCities.count < 4 else { return }
        guard !selectedCities.contains(where: { $0.placeID == suggestion.placeID }) else {
            return
        }
        selectedCities.append(suggestion)
        cityQuery = ""
        citySuggestions = []
        citySearchMessage = nil
    }

    func removeCity(_ suggestion: CitySuggestion) {
        selectedCities.removeAll { $0.placeID == suggestion.placeID }
    }

    func createTrip() async -> TripSession? {
        guard canSubmit else { return nil }
        isSubmitting = true
        defer { isSubmitting = false }

        let request = TripCreateRequest(
            cities: cityNames,
            cityPlaceIDs: cityPlaceIDs,
            country: trimmedCountry,
            startDate: apiDate(startDate),
            endDate: apiDate(endDate),
            creatorName: creatorName.trimmingCharacters(in: .whitespacesAndNewlines),
            creatorHomeCity: optionalText(creatorHomeCity),
            creatorInterests: interestSelection.values(in: PreferenceCatalog.interests),
            creatorDietaryExcludes: dietarySelection.values(
                in: PreferenceCatalog.dietaryExcludes
            )
        )

        do {
            let response = try await apiClient.createTrip(request)
            _ = try await apiClient.gather(tripID: response.trip.id)
            return TripSession(
                trip: response.trip,
                travelerID: response.travelerID,
                planRequest: PlanRequest(
                    dayStart: apiTime(dayStart),
                    dayEnd: apiTime(dayEnd)
                )
            )
        } catch {
            show(error)
            return nil
        }
    }

    private func apiDate(_ date: Date) -> String {
        date.formatted(.iso8601.year().month().day().dateSeparator(.dash))
    }

    private func apiTime(_ date: Date) -> String {
        let components = Calendar.current.dateComponents([.hour, .minute], from: date)
        let hour = components.hour ?? 0
        let minute = components.minute ?? 0
        let hourPrefix = hour < 10 ? "0" : ""
        let minutePrefix = minute < 10 ? "0" : ""
        return "\(hourPrefix)\(hour):\(minutePrefix)\(minute):00"
    }

    private func minuteOfDay(_ date: Date) -> Int {
        let components = Calendar.current.dateComponents([.hour, .minute], from: date)
        return (components.hour ?? 0) * 60 + (components.minute ?? 0)
    }

    private func optionalText(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        isShowingError = true
    }
}
