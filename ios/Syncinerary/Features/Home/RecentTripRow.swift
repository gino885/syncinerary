import SwiftUI

/// A journal entry: where, when, and the stamp of how far it has got.
struct RecentTripRow: View {
    let session: TripSession

    var body: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 2) {
                Text(session.trip.destination)
                    .font(AppType.subtitle)
                    .foregroundStyle(AppTheme.ink)
                MetaLabel("\(TripDate.range(session.trip.startDate, session.trip.endDate)) · \(session.trip.days) days")
            }
            Spacer(minLength: AppTheme.spacingM)
            StampView(mark: stamp, scale: 0.62, isDecorative: false)
        }
        .padding(.vertical, AppTheme.spacingXS)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
        .accessibilityHint("Continues this trip where it left off")
    }

    private var stamp: StampMark {
        switch session.trip.status {
        case "swiping": .stage("Swiping", ink: AppTheme.stamp)
        case "shortlisting": .stage("Voting", ink: AppTheme.violet)
        case "scheduling": .stage("Stay", ink: AppTheme.violet)
        case "active": .stage("Planned", ink: AppTheme.jade)
        case "disrupted": .stage("Changed", ink: AppTheme.stamp)
        default: .stage("Gathering", ink: AppTheme.faded)
        }
    }
}

#Preview {
    List {
        RecentTripRow(
            session: TripSession(
                trip: TripSummary(id: UUID(), destination: "Sapporo, Otaru", cities: ["Sapporo", "Otaru"], country: "Japan", timezone: "Asia/Tokyo", startDate: "2026-09-25", endDate: "2026-09-29", days: 5, status: "swiping"),
                travelerID: UUID(),
                planRequest: .standard
            )
        )
    }
}
