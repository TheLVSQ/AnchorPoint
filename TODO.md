# AnchorPoint TODO

## Enhancements to Add

- [x] Google Authentication (SSO)
- [ ] Embed code generator for event info
- [x] Add live results to people search
- [ ] Review design: modernize to be visually appealing but not overwhelming

- [ ] Email: Add ability to send emails (transactional + blast)

- [ ] Check-in
-- [ ] Printer connection/setup
-- [ ] Create Room flow > Age/Grade Auto-Assignment
--- [ ] Change Min/Max to a dropdown with values for K-12
--- [ ] Make the 'Active' checkbox for the room availability next to the word 'Active' and make it hard to miss

- [ ] User Permissions
-- [ ] Change page to show only one save button, not one save per person
-- [ ] Update page to be something other than all users view.

- [x] UI Enhancements
-- [x] Add Favicon
-- [ ] Overall UI Review and refresh
-- [ ] Create Group Form -> Group Status: change status checkbox to dropdown
-- [x] Phone Blasts: show stats (answered, no answer, etc)
-- [x] Phone Blasts: show live progress
-- [ ] Add Person menu:
--- [ ] Make "Status" a dropdown with pre-populated choices instead of a free-form text box.
--- [ ] Phone number entry box could use some formatting (dynamic or other)
--- [ ] Email entry box should check for email in correct format, error if not
-- [x] Add User Page:
--- [x] Check to see if info matches a current person record as it is being entered
--- [x] Login should be user's email address, email address should not be optional
--- [ ] State selection for address should be a pre-populated dropdown of states to ensure consistency
--- [x] If a Person exists for a new User, merge or allow the Person/User records to coexist
--- [ ] When updating a user's Role, clicking the save should have a confirmation alert


- Security
-- [ ] Overall security review before making repo public

## Bugs to Squash

- [x] Mobile navigation menu doesn't scroll on mobile
- [x] Groups list page doesn't allow you to view details of a group
- [x] Groups: Unclear how to manage group users

## In Progress

- [ ] Beta testing with users
- [ ] Bulk import API (spec written, plan written — implementation pending)


## Completed

- [x] Add Gender to people records
- [x] Add indicator for adults vs minors
- [x] Google SSO (bolivar.church domain only)
- [x] Pagination on people and groups lists
- [x] Database indexes (Person.email, checkin N+1 fixes)
- [x] Messaging service tests
- [x] Extract duplicate recipient query logic
- [x] Phone blast stats and live progress
- [x] Group detail, edit, delete, member management
- [x] User creation flow — email as login, Person linking
- [x] Live people search (HTMX)
- [x] Mobile nav scroll fix
- [x] Media files served in production
- [x] Org logo display fix
