import Foundation
import Observation

@MainActor
@Observable
final class TripCreateViewModel {
    var destination = "Hokkaido"
    var creatorName = ""
    var creatorHomeCity = ""
    var startDate: Date
    var endDate: Date
    var dayStart: Date
    var dayEnd: Date
    var isSubmitting = false
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

    var canSubmit: Bool {
        !destination.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !creatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && endDate >= startDate
            && minuteOfDay(dayEnd) > minuteOfDay(dayStart)
            && !isSubmitting
    }

    func adjustEndDate() {
        guard endDate < startDate else { return }
        endDate = Calendar.current.date(byAdding: .day, value: 4, to: startDate) ?? startDate
    }

    func createTrip() async -> TripSession? {
        guard canSubmit else { return nil }
        isSubmitting = true
        defer { isSubmitting = false }

        let request = TripCreateRequest(
            destination: destination.trimmingCharacters(in: .whitespacesAndNewlines),
            startDate: apiDate(startDate),
            endDate: apiDate(endDate),
            creatorName: creatorName.trimmingCharacters(in: .whitespacesAndNewlines),
            creatorHomeCity: optionalText(creatorHomeCity)
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
