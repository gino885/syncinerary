import SwiftUI

struct TripsBoardView: View {
    @Environment(AccountStore.self) private var accounts
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hasAppeared = false
    @State private var isShowingAccountSettings = false

    let onOpen: (TripListRow) -> Void
    let onCreate: () -> Void
    let onJoin: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 32) {
                HStack {
                    Text("Trips").font(.headline)
                    Spacer()
                    if let name = accounts.account?.displayName {
                        Menu {
                            Button("Account settings", systemImage: "person.crop.circle") {
                                isShowingAccountSettings = true
                            }
                            Button("Sign out", systemImage: "rectangle.portrait.and.arrow.right") {
                                Task { await accounts.signOut() }
                            }.disabled(accounts.isWorking)
                        } label: {
                        Text(name)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.faded)
                            .lineLimit(1)
                            .frame(minHeight: 44)
                        }.accessibilityLabel("Account")
                    }
                }
                VStack(alignment: .leading, spacing: 12) {
                    Text("Your next chapter.")
                        .font(AppType.title)
                        .foregroundStyle(AppTheme.accent)
                    Text("Good places. Your people. One trip.")
                        .font(.title3)
                        .foregroundStyle(AppTheme.faded)
                }
                .padding(.vertical, 24)
                if let error = accounts.errorMessage {
                    Text(error).font(.callout).foregroundStyle(AppTheme.stamp)
                    Button("Try again") { Task { await accounts.loadTrips() } }
                        .frame(minHeight: 44)
                }
                if accounts.trips.isEmpty {
                    ContentUnavailableView {
                        Label("Where to next?", systemImage: "suitcase.rolling")
                    } description: {
                        Text("Start a trip or bring your friends’ plan along.")
                    }
                } else {
                    LazyVStack(spacing: 12) {
                        ForEach(accounts.trips) { trip in
                            Button { onOpen(trip) } label: { TripDepartureRow(trip: trip) }
                                .buttonStyle(PressFeedbackStyle())
                        }
                    }
                }
            }
            .padding(24)
            .opacity(hasAppeared ? 1 : 0)
            .offset(y: hasAppeared || reduceMotion ? 0 : 14)
        }
        .foregroundStyle(AppTheme.ink)
        .background(AppTheme.canvas.ignoresSafeArea())
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 8) {
                Button("New trip", systemImage: "arrow.up.right", action: onCreate)
                    .buttonStyle(JourneyButtonStyle())
                Button("Join with code", action: onJoin)
                    .font(.headline)
                    .frame(minHeight: 44)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)
            .background(.regularMaterial)
        }
        .task {
            withAnimation(reduceMotion ? AppTheme.fade : .smooth(duration: 0.45)) {
                hasAppeared = true
            }
            await accounts.loadTrips()
        }
        .refreshable { await accounts.loadTrips() }
        .sheet(isPresented: $isShowingAccountSettings) {
            AccountSettingsView()
        }
    }
}
