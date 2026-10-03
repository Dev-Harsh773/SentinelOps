package com.sentinelops.mobile.ui.incidents;

import static org.junit.Assert.*;

import org.junit.Test;

public class IncidentLifecyclePresentationTest {

    static class ActionAvailability {
        final boolean canInvestigate;
        final boolean canResolve;
        final boolean canClose;

        ActionAvailability(boolean canInvestigate, boolean canResolve, boolean canClose) {
            this.canInvestigate = canInvestigate;
            this.canResolve = canResolve;
            this.canClose = canClose;
        }

        static ActionAvailability forState(String status, boolean isOnline) {
            if (!isOnline) {
                return new ActionAvailability(false, false, false);
            }
            if (status == null) {
                return new ActionAvailability(false, false, false);
            }
            String st = status.toLowerCase().trim();
            switch (st) {
                case "open":
                    return new ActionAvailability(true, true, false);
                case "investigating":
                    return new ActionAvailability(false, true, false);
                case "resolved":
                    return new ActionAvailability(false, false, true);
                case "closed":
                default:
                    return new ActionAvailability(false, false, false);
            }
        }
    }

    @Test
    public void testOpenStateOnline() {
        ActionAvailability actions = ActionAvailability.forState("open", true);
        assertTrue("OPEN status should allow Investigate", actions.canInvestigate);
        assertTrue("OPEN status should allow Resolve", actions.canResolve);
        assertFalse("OPEN status should not allow Close", actions.canClose);
    }

    @Test
    public void testInvestigatingStateOnline() {
        ActionAvailability actions = ActionAvailability.forState("investigating", true);
        assertFalse("INVESTIGATING status should not allow Investigate", actions.canInvestigate);
        assertTrue("INVESTIGATING status should allow Resolve", actions.canResolve);
        assertFalse("INVESTIGATING status should not allow Close", actions.canClose);
    }

    @Test
    public void testResolvedStateOnline() {
        ActionAvailability actions = ActionAvailability.forState("resolved", true);
        assertFalse("RESOLVED status should not allow Investigate", actions.canInvestigate);
        assertFalse("RESOLVED status should not allow Resolve", actions.canResolve);
        assertTrue("RESOLVED status should allow Close", actions.canClose);
    }

    @Test
    public void testClosedStateOnline() {
        ActionAvailability actions = ActionAvailability.forState("closed", true);
        assertFalse("CLOSED status should not allow Investigate", actions.canInvestigate);
        assertFalse("CLOSED status should not allow Resolve", actions.canResolve);
        assertFalse("CLOSED status should not allow Close", actions.canClose);
    }

    @Test
    public void testOfflineDisablesAllActions() {
        ActionAvailability openOffline = ActionAvailability.forState("open", false);
        assertFalse(openOffline.canInvestigate);
        assertFalse(openOffline.canResolve);
        assertFalse(openOffline.canClose);

        ActionAvailability investigatingOffline = ActionAvailability.forState("investigating", false);
        assertFalse(investigatingOffline.canResolve);

        ActionAvailability resolvedOffline = ActionAvailability.forState("resolved", false);
        assertFalse(resolvedOffline.canClose);
    }
}
