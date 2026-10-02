import SwiftUI

/// Shared canvas and navigation surfaces for lists and forms.
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
    /// A screen using the shared travel canvas.
    func journalPage() -> some View {
        modifier(JournalPage())
    }

    /// The background surrounding a row's own content.
    func journalRow() -> some View {
        listRowBackground(AppTheme.paper)
    }
}
