import SwiftUI

/// A departure board: hairline rows, destination in the display serif on the
/// left, dates and party size in monospace on the right. No cards, because
/// every other list in this app is already ruled rows.
struct TripsBoardView: View {
    @Environment(AccountStore.self) private var accounts

    let onOpen: (TripListRow) -> Void
    let onCreate: () -> Void
    let onJoin: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            if accounts.trips.isEmpty {
                Text("No trips yet. Start one, or join with a code.")
                    .font(AppType.body)
                    .foregroundStyle(AppTheme.faded)
                    .padding(.vertical, AppTheme.spacingXL)
            } else {
                ForEach(accounts.trips) { trip in
                    Button { onOpen(trip) } label: { row(trip) }
                        .buttonStyle(.plain)
                    Rectangle()
                        .fill(AppTheme.rule)
                        .frame(height: AppTheme.hairlineWidth)
                }
            }

            Spacer()

            HStack(spacing: AppTheme.spacingM) {
                Button("New trip", action: onCreate)
                    .buttonStyle(StampButtonStyle())
                Button("Join with code", action: onJoin)
                    .font(AppType.rowTitle)
                    .foregroundStyle(AppTheme.ink)
            }
        }
        .padding(AppTheme.spacingL)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.paper)
        .task { await accounts.loadTrips() }
        .refreshable { await accounts.loadTrips() }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("Trips")
                .font(AppType.title)
                .foregroundStyle(AppTheme.ink)
            Spacer()
            if let handle = accounts.account?.handle {
                Text("@\(handle)")
                    .font(AppType.mono)
                    .foregroundStyle(AppTheme.faded)
            }
        }
        .padding(.bottom, AppTheme.spacingL)
    }

    private func row(_ trip: TripListRow) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: AppTheme.spacingM) {
            VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
                Text(trip.destination)
                    .font(AppType.dayDate)
                    .foregroundStyle(AppTheme.ink)
                    .multilineTextAlignment(.leading)
                Text(partyLine(trip))
                    .font(AppType.mono)
                    .foregroundStyle(AppTheme.faded)
            }
            Spacer(minLength: AppTheme.spacingM)
            VStack(alignment: .trailing, spacing: AppTheme.spacingXS) {
                Text(TripDate.parse(trip.startDate)?.formatted(TripDate.short)
                    ?? trip.startDate)
                    .font(AppType.mono)
                    .monospacedDigit()
                    .foregroundStyle(AppTheme.ink)
                if trip.status == "active" {
                    StampView(mark: .stage("Active", ink: AppTheme.jade), scale: 0.7)
                }
            }
        }
        .padding(.vertical, AppTheme.spacingM)
        .contentShape(Rectangle())
    }

    private func partyLine(_ trip: TripListRow) -> String {
        let party = trip.memberCount == 1 ? "1 traveller" : "\(trip.memberCount) travellers"
        return "\(trip.days)d · \(party)"
    }
}
