import SwiftUI

struct TripCreateView: View {
    let onCreated: (TripSession) -> Void

    @State private var viewModel = TripCreateViewModel()

    var body: some View {
        @Bindable var viewModel = viewModel

        Form {
            Section("Trip") {
                TextField("Country", text: $viewModel.country)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled()
                TextField(
                    "Cities, separated by commas",
                    text: $viewModel.cities,
                    axis: .vertical
                )
                .lineLimit(1...3)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled()
                Text("One country per trip, then the cities in it, for example: Japan, then Sapporo, Otaru. Each city gets its own run of days rather than being visited on alternate days.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                DatePicker(
                    "Start date",
                    selection: $viewModel.startDate,
                    displayedComponents: .date
                )
                DatePicker(
                    "End date",
                    selection: $viewModel.endDate,
                    in: viewModel.startDate...,
                    displayedComponents: .date
                )
            }

            Section("Traveler") {
                TextField("Your name", text: $viewModel.creatorName)
                    .textContentType(.name)
                TextField("Home city (optional)", text: $viewModel.creatorHomeCity)
                    .textContentType(.addressCity)
            }

            Section("Your travel style") {
                TextField(
                    "Interests, separated by commas",
                    text: $viewModel.interests,
                    axis: .vertical
                )
                .lineLimit(2...4)
                TextField(
                    "Foods to avoid, separated by commas",
                    text: $viewModel.dietaryExcludes,
                    axis: .vertical
                )
                .lineLimit(2...4)
                Text("Examples: coffee, architecture, seafood, peanuts. Unknown restaurant details will be shown with a reminder to confirm directly.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section("Daily schedule") {
                DatePicker(
                    "Start exploring",
                    selection: $viewModel.dayStart,
                    displayedComponents: .hourAndMinute
                )
                DatePicker(
                    "Finish by",
                    selection: $viewModel.dayEnd,
                    displayedComponents: .hourAndMinute
                )
                Text("The default is 8:00 AM to 9:00 PM, which leaves room for dinner. You can adjust it for this trip.")
                    .foregroundStyle(.secondary)
            }

            Section {
                Button(action: createTrip) {
                    if viewModel.isSubmitting {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Create trip", systemImage: "airplane.departure")
                            .frame(maxWidth: .infinity)
                    }
                }
                .disabled(!viewModel.canSubmit)
                .frame(minHeight: AppLayout.minimumTapHeight)
            }
        }
        .navigationTitle("Plan a trip")
        .onChange(of: viewModel.startDate) {
            viewModel.adjustEndDate()
        }
        .alert("Couldn’t create trip", isPresented: $viewModel.isShowingError) { } message: {
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
        TripCreateView(onCreated: { _ in })
    }
}
