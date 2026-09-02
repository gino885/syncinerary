import SwiftUI

struct TripCreateView: View {
    let onCreated: (TripSession) -> Void
    let onResume: (TripSession) -> Void

    @State private var viewModel = TripCreateViewModel()
    @State private var isShowingPreferences = false
    @Environment(RecentTripsStore.self) private var recentTrips

    var body: some View {
        @Bindable var viewModel = viewModel

        Form {
            WhereToHeader()
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())

            RecentTripsSection(
                sessions: recentTrips.sessions,
                onResume: onResume,
                onForget: recentTrips.forget
            )

            Section {
                TextField("Country, for example Japan", text: $viewModel.country)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled()
                CityPickerView(viewModel: viewModel)
                DatePicker("From", selection: $viewModel.startDate, displayedComponents: .date)
                DatePicker("To", selection: $viewModel.endDate, in: viewModel.startDate..., displayedComponents: .date)
            } header: {
                EyebrowText("Trip")
            }

            Section {
                TextField("Your name", text: $viewModel.creatorName)
                    .textContentType(.name)
                TextField("Home city, optional", text: $viewModel.creatorHomeCity)
                    .textContentType(.addressCity)
            } header: {
                EyebrowText("You")
            }

            Section {
                Button(action: showPreferences) {
                    PreferenceSummaryRow(summary: viewModel.preferenceSummary)
                }
                .buttonStyle(.plain)
            } header: {
                EyebrowText("Preferences")
            }

            Section {
                DatePicker("Start the day", selection: $viewModel.dayStart, displayedComponents: .hourAndMinute)
                DatePicker("Finish by", selection: $viewModel.dayEnd, displayedComponents: .hourAndMinute)
            } header: {
                EyebrowText("Hours")
            }

            Section {
                Button(action: createTrip) {
                    if viewModel.isSubmitting {
                        ProgressView()
                            .tint(AppTheme.stamp)
                    } else {
                        Text("Find places")
                    }
                }
                .buttonStyle(.stamp)
                .disabled(!viewModel.canSubmit)
                .listRowBackground(Color.clear)
                .listRowInsets(ListRowInsets.stamp)
            }
        }
        .journalPage()
        .navigationTitle("Syncinerary")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: viewModel.startDate) {
            viewModel.adjustEndDate()
        }
        .onChange(of: viewModel.country) {
            viewModel.countryChanged()
        }
        .alert("Couldn't create the trip", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
        .sheet(isPresented: $isShowingPreferences) {
            PreferencePickerSheet(
                interests: $viewModel.interestSelection,
                dietaryExcludes: $viewModel.dietarySelection
            )
        }
    }

    private func createTrip() {
        Task {
            if let session = await viewModel.createTrip() {
                onCreated(session)
            }
        }
    }

    private func showPreferences() {
        isShowingPreferences = true
    }
}

#Preview {
    NavigationStack {
        TripCreateView(onCreated: { _ in }, onResume: { _ in })
    }
    .environment(RecentTripsStore())
}
