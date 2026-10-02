import Foundation

@main
@MainActor
enum CityDaysTests {
    static func main() throws {
        let model = TripCreateViewModel()
        let calendar = Calendar.current
        model.startDate = calendar.date(from: DateComponents(year: 2026, month: 10, day: 1))!
        model.endDate = calendar.date(from: DateComponents(year: 2026, month: 10, day: 5))!
        model.country = "Japan"
        model.creatorName = "Leader"
        let cities = ["Tokyo", "Atami", "Kamakura"].map {
            CitySuggestion(placeID: $0, name: $0, subtitle: nil)
        }
        for city in cities { model.selectCity(city) }
        precondition(model.effectiveCityDays == [2, 2, 1])
        model.setCityDays(3, at: 0)
        precondition(!model.canSubmit, "An overallocated trip must not submit")
        model.setCityDays(1, at: 1)
        precondition(model.effectiveCityDays == [3, 1, 1] && model.canSubmit)
        model.mainCityID = "Atami"
        precondition(model.effectiveCityDays == [3, 1, 1], "Priority must not overwrite explicit days")
        model.endDate = calendar.date(byAdding: .day, value: 1, to: model.endDate)!
        precondition(!model.canSubmit, "Changing dates must revalidate the allocation")
        model.cityDays = []
        precondition(model.effectiveCityDays == [2, 2, 2] && model.canSubmit)
        model.removeCity(cities[1])
        precondition(model.mainCityID.isEmpty && model.effectiveCityDays == [3, 3])

        let request = TripCreateRequest(
            cities: ["Tokyo", "Atami", "Kamakura"], cityPlaceIDs: ["t", "a", "k"],
            country: "Japan", startDate: "2026-10-01", endDate: "2026-10-05",
            creatorName: "Leader", creatorHomeCity: nil, creatorInterests: [],
            creatorDietaryExcludes: [], outputLocale: "zh-Hant", cityDays: [3, 1, 1],
            priorityCityIndex: 0
        )
        let body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as! [String: Any]
        precondition(body["city_days"] as? [Int] == [3, 1, 1])
        precondition(body["priority_city_index"] as? Int == 0)
        precondition(body["output_locale"] as? String == "zh-Hant")
        print("iOS city day tests passed")
    }
}
