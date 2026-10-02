import SwiftUI

struct ItineraryStopEditor: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var stop: ItineraryDraftStop
    let days: [ItineraryDay]
    let isNew: Bool
    let onSave: (ItineraryDraftStop) -> Void

    init(stop: ItineraryDraftStop, days: [ItineraryDay], isNew: Bool,
         onSave: @escaping (ItineraryDraftStop) -> Void) {
        _stop = State(initialValue: stop)
        self.days = days
        self.isNew = isNew
        self.onSave = onSave
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(stop.name).font(AppType.dayDate).foregroundStyle(AppTheme.ink)
                        Text(stop.timeRange)
                            .font(.title3.monospacedDigit().bold())
                            .foregroundStyle(AppTheme.accent)
                            .contentTransition(reduceMotion ? .identity : .numericText())
                    }
                    .padding(.vertical, 8)
                    .listRowBackground(AppTheme.canvas)
                }
                Section {
                    Picker("Day", selection: $stop.day) {
                        ForEach(days) { day in Text("Day \(day.day + 1)").tag(day.day) }
                    }
                    Picker("Start time", selection: $stop.startMinute) {
                        ForEach(Array(stride(from: 0, to: 1440, by: 30)), id: \.self) { minute in
                            Text(ItineraryDraftStop.clock(minute)).tag(minute)
                        }
                    }
                    Stepper(value: $stop.durationMinutes, in: 30...720, step: 30) {
                        Text("\(stop.durationMinutes) minutes")
                    }
                    .accessibilityLabel("Visit duration")
                    .accessibilityValue("\(stop.durationMinutes) minutes")
                }
                .disabled(stop.fixed)
                if stop.fixed { Text("This stop has a fixed reservation.") }
                if stop.endMinute >= 1440 { Text("The visit must finish before midnight.").foregroundStyle(AppTheme.stamp) }
            }
            .journalPage()
            .animation(reduceMotion ? nil : AppTheme.selection, value: stop.durationMinutes)
            .sensoryFeedback(.selection, trigger: stop.durationMinutes)
            .navigationTitle(isNew ? Text("Add a place") : Text("Edit stop"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { onSave(stop); dismiss() }
                        .disabled(stop.fixed || stop.endMinute >= 1440)
                }
            }
        }
    }
}
