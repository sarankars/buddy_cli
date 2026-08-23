use buddy::enhancer::RuleBasedEnhancer;

#[test]
fn test_rule_based_enhancer_preserves_prompt() {
    let enhancer = RuleBasedEnhancer::new();
    let prompt = "Explain recursion with examples.";
    let enhanced = enhancer.enhance(prompt).unwrap();

    assert!(enhanced.contains("Please carry out the request below."));
    assert!(enhanced.contains("Request:\nExplain recursion with examples."));
}

#[test]
fn test_rule_based_enhancer_empty_rejected() {
    let enhancer = RuleBasedEnhancer::new();
    assert!(enhancer.enhance("").is_err());
    assert!(enhancer.enhance("   \n\t  ").is_err());
}
