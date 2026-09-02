import SwiftUI

/// The longest wait in the app, given words on a board.
struct GatheringView: View {
    let onGathered: (TripSession) -> Void

    @State private var viewModel: GatheringViewModel

    init(session: TripSession, onGathered: @escaping (TripSession) -> Void) {
        self.onGathered = onGathered
        _viewModel = State(initialValue: GatheringViewModel(session: session))
    }

    var body: some View {
        Group {
            if let message = viewModel.errorMessage {
                ContentUnavailableView {
                    Label("Couldn't find places", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(message)
                } actions: {
                    Button("Try again", action: retry)
                        .buttonStyle(.stamp)
                        .frame(maxWidth: 240)
                }
            } else {
                FunLoadingView(script: .gathering(city: viewModel.cityName))
                    .ignoresSafeArea()
            }
        }
        .background(AppTheme.paper.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .task {
            await run()
        }
    }

    private func retry() {
        Task {
            await run()
        }
    }

    private func run() async {
        if await viewModel.gather() {
            onGathered(viewModel.session)
        }
    }
}
