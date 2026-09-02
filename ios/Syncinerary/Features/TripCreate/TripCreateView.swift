import SwiftUI

struct TripCreateView: View {
    let onCreated: (TripSession) -> Void
    let onResume: (TripSession) -> Void

    @State private var viewModel = TripCreateViewModel()
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
                TextField("Cities, comma separated: Sapporo, Otaru", text: $viewModel.cities, axis: .vertical)
                    .lineLimit(1...3)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled()
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
                TextField("Interests: coffee, architecture, seafood", text: $viewModel.interests, axis: .vertical)
                    .lineLimit(1...3)
                TextField("Foods to avoid: peanuts, shellfish", text: $viewModel.dietaryExcludes, axis: .vertical)
                    .lineLimit(1...3)
            } header: {
                EyebrowText("You")
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
        .alert("Couldn't create the trip", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    private func createTrip() {
        Task {
            if let session = await viewModel.createTrip() {
                onCreated(session)
            }
        }
    }
}

#Preview {
    NavigationStack {
        TripCreateView(onCreated: { _ in }, onResume: { _ in })
    }
    .environment(RecentTripsStore())
}
