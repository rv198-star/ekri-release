# Mercury Deployment Policy

Production deployment admission is a separate governance decision. Test success is necessary evidence but is not production approval.

Platform Operations owns the final production deployment admission decision. Release automation may prepare and submit a deployment candidate, but it cannot approve production deployment on its own.

The current pipeline declaration still names release automation as the deploy-admission owner. Until that conflict is reconciled, downstream consumers must preserve both owner claims and must not treat either claim as sole accepted deployment authority.
