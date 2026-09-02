import SwiftUI

/// Puts a screen on paper: the ground, the scroll and toolbar surfaces, and
/// the ink the navigation bar draws with. Applied to every screen so no
/// screen falls back to the system's grouped grey.
private struct JournalPage: ViewModifier {
    func body(content: Content) -> some View {
        content
            .scrollContentBackground(.hidden)
            .background(AppTheme.paper.ignoresSafeArea())
            .toolbarBackground(AppTheme.paper, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
    }
}

extension View {
    /// A screen written on the journal's paper.
    func journalPage() -> some View {
        modifier(JournalPage())
    }

    /// Rows that sit on the page rather than on their own white cards.
    func journalRow() -> some View {
        listRowBackground(AppTheme.paper)
    }
}
