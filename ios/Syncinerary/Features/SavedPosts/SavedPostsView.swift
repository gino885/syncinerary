import SwiftUI

struct SavedPostsView: View {
    let onContinue: (TripSession) -> Void

    @State private var viewModel: SavedPostsViewModel

    init(session: TripSession, onContinue: @escaping (TripSession) -> Void) {
        self.onContinue = onContinue
        _viewModel = State(initialValue: SavedPostsViewModel(session: session))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Form {
            FriendsPlanningHeader()
                .listRowBackground(Color.clear)

            Section("Saved post") {
                TextField("Instagram, TikTok, or RedNote link", text: $viewModel.postURL)
                    .textContentType(.URL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()

                TextField("Place or restaurant name (optional)", text: $viewModel.placeName)
                    .textContentType(.location)

                Button("Add saved post", systemImage: "link.badge.plus", action: attach)
                    .disabled(!viewModel.canAttach)
                    .frame(minHeight: AppLayout.minimumTapHeight)
            }

            if !viewModel.attachments.isEmpty {
                Section("Added by your group") {
                    ForEach(viewModel.attachments) { attachment in
                        AttachedPostRow(attachment: attachment)
                    }
                }
            }

            Section {
                Button("Start swiping", systemImage: "person.3.fill", action: continueToSwipe)
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity, minHeight: AppLayout.minimumTapHeight)
            } footer: {
                Text("Saved posts are optional. You can continue with the places already gathered.")
            }
        }
        .navigationTitle("Plan together")
        .navigationBarBackButtonHidden(true)
        .alert("Couldn’t add this post", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    private func attach() {
        Task { await viewModel.attach() }
    }

    private func continueToSwipe() {
        onContinue(viewModel.session)
    }
}

#Preview {
    NavigationStack {
        SavedPostsView(
            session: TripSession(
                trip: TripSummary(
                    id: UUID(),
                    destination: "Sapporo, Otaru",
                    cities: ["Sapporo", "Otaru"],
                    country: "Japan",
                    timezone: "Asia/Tokyo",
                    startDate: "2026-09-25",
                    endDate: "2026-09-29",
                    days: 5,
                    status: "setup"
                ),
                travelerID: UUID(),
                planRequest: .standard
            ),
            onContinue: { _ in }
        )
    }
}
