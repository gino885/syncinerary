import SwiftUI

struct CityDaysSection: View {
    @Bindable var viewModel: TripCreateViewModel

    var body: some View {
        if !viewModel.selectedCities.isEmpty {
            Section {
                ForEach(Array(viewModel.selectedCities.enumerated()), id: \.element.id) { index, city in
                    Stepper(value: days(at: index), in: 1...max(1, viewModel.tripDays)) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(city.name)
                            Text("\(viewModel.effectiveCityDays[index]) days")
                                .monospacedDigit()
                                .foregroundStyle(AppTheme.faded)
                        }
                    }
                    .accessibilityLabel("Days in \(city.name)")
                    .accessibilityValue("\(viewModel.effectiveCityDays[index]) days")
                }
                if viewModel.selectedCities.count > 1 {
                    Picker("Main city", selection: $viewModel.mainCityID) {
                        Text("No preference").tag("")
                        ForEach(viewModel.selectedCities) { city in
                            Text(city.name).tag(city.placeID)
                        }
                    }
                }
                if !viewModel.cityDaysAreValid {
                    Button("Distribute days") { viewModel.cityDays = [] }
                }
            } header: {
                Text("Days per city")
            } footer: {
                Text("\(viewModel.allocatedDays) of \(viewModel.tripDays) days assigned")
            }
        }
    }

    private func days(at index: Int) -> Binding<Int> {
        Binding(get: { viewModel.effectiveCityDays[index] },
                set: { viewModel.setCityDays($0, at: index) })
    }
}
