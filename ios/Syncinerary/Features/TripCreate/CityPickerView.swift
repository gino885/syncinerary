import SwiftUI

struct CityPickerView: View {
    @Bindable var viewModel: TripCreateViewModel

    var body: some View {
        if !viewModel.selectedCities.isEmpty {
            Text("Selected cities")
                .font(.caption)
                .foregroundStyle(AppTheme.faded)

            ForEach(viewModel.selectedCities) { city in
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(city.name)
                        if let subtitle = city.subtitle {
                            Text(subtitle)
                                .font(.caption)
                                .foregroundStyle(AppTheme.faded)
                        }
                    }
                    Spacer()
                    Button("Remove \(city.name)", systemImage: "xmark.circle") {
                        viewModel.removeCity(city)
                    }
                    .labelStyle(.iconOnly)
                    .font(.title3)
                    .foregroundStyle(AppTheme.faded)
                    .accessibilityLabel("Remove \(city.name)")
                }
                .frame(minHeight: 44)
            }
        }

        TextField("City name, for example Tokyo", text: $viewModel.cityQuery)
            .textContentType(.addressCity)
            .textInputAutocapitalization(.words)
            .autocorrectionDisabled()
            .submitLabel(.search)
            .onSubmit(search)

        Button(action: search) {
            if viewModel.isSearchingCities {
                ProgressView()
            } else {
                Label("Search cities", systemImage: "magnifyingglass")
            }
        }
        .disabled(!viewModel.canSearchCities)

        ForEach(viewModel.citySuggestions) { city in
            Button {
                viewModel.selectCity(city)
            } label: {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(city.name)
                            .foregroundStyle(AppTheme.ink)
                        if let subtitle = city.subtitle {
                            Text(subtitle)
                                .font(.caption)
                                .foregroundStyle(AppTheme.faded)
                        }
                    }
                    Spacer()
                    Image(systemName: "plus.circle")
                        .foregroundStyle(AppTheme.jade)
                }
                .contentShape(Rectangle())
                .frame(minHeight: 44)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Add \(city.name)")
        }

        if !viewModel.citySuggestions.isEmpty {
            Text("City suggestions from Google Maps")
                .font(.caption2)
                .foregroundStyle(AppTheme.faded)
        }

        if let message = viewModel.citySearchMessage {
            Text(message)
                .font(.caption)
                .foregroundStyle(AppTheme.stamp)
        }
    }

    private func search() {
        Task {
            await viewModel.searchCities()
        }
    }
}
